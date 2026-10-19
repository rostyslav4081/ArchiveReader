using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Text.Json.Nodes;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using System.Windows.Shapes;
using System.Windows.Documents;
using Microsoft.Win32;

namespace ArchiveReader;

public record RegionItem(JsonObject Data)
{
    public string Id => Data["id"]?.ToString() ?? "";
    public string Label => Data["kind"]==null ? Data["label"]?.ToString() ?? "" : (Data["reading_order"]!=null ? Data["reading_order"]+" · " : "")+Localizer.Text(Data["kind"]?.ToString() switch { "line"=>"Рядок", "entry"=>"Запис", "column"=>"Колонка", "missing"=>"Відсутній фрагмент", _=>"Пошкодження" })+(Data["label"]?.ToString() is string label && label.Length>0 ? " · "+label : "");
}
public record ComparisonItem(JsonObject Data)
{
    public string Label => Data["id"]!.ToString()+" · "+Localizer.Text(Data["disagreement"]?.GetValue<bool>()==true ? "Є розбіжності" : "Прочитання збігаються");
}
public record NameMatch(JsonObject Data)
{
    public string Label => $"{Data["name"]} · {Data["document"]} · {Localizer.Text("Стор.")} {Data["number"]} · {Data["similarity"]}";
}

public partial class WorkbenchWindow : Window
{
    readonly PageItem page;
    readonly Func<string,JsonObject?,CancellationToken,Task<JsonNode>> worker;
    CancellationTokenSource? work;
    Point? drag;
    Rect? rectangle;
    string? selectedRegion, reportPath;
    bool filling, busy;
    List<RegionItem> regions=[];
    readonly List<Point> points=[];
    JsonObject? photo;
    public string? SelectedPageId { get; private set; }
    public string? SelectedRecordId { get; private set; }
    static string T(string s)=>Localizer.Text(s);
    static string F(string s,params object?[] args)=>Localizer.Format(s,args);
    static string SelectedTag(ComboBox box)=>((ComboBoxItem)box.SelectedItem).Tag.ToString()!;
    Task<JsonNode> Call(string command,JsonObject? args=null)=>worker(command,args,work?.Token ?? default);

    public WorkbenchWindow(PageItem page,Func<string,JsonObject?,CancellationToken,Task<JsonNode>> worker,string model,string? initialRegion=null,bool openRecognition=false)
    {
        this.page=page; this.worker=worker;
        InitializeComponent();
        DocumentTitle.Text=$"{page.Name} · {T("Стор.")} {page.Num+1}";
        ModelA.Text=model;
        ModelB.Text=""; // The user chooses a language-appropriate comparison model.
        Loaded+=async (_,_)=>await Run(async()=>
        {
            Localizer.Apply(this,Localizer.Language);
            var rendering=await Call("render",new() { ["id"]=page.Id });
            var bitmap=Bitmap(rendering["path"]!.ToString());
            PageImage.Source=bitmap;
            Surface.Height=PageImage.Height=600*bitmap.PixelHeight/bitmap.PixelWidth;
            await RefreshRegions();
            var details=await Call("details",new() { ["id"]=page.Id });
            LinkedRecord.ItemsSource=new[] { new RecordItem(new JsonObject { ["person"]=T("Без зв'язку") }) }.Concat(details["records"]!.AsArray().Select(n=>new RecordItem(n!.AsObject()))).ToList();
            LinkedRecord.SelectedIndex=0;
            if(initialRegion!=null) Regions.SelectedItem=regions.FirstOrDefault(r=>r.Id==initialRegion);
            if(openRecognition)Tabs.SelectedIndex=6;
            var profile=await Call("book_profile",new() { ["id"]=page.Id });
            BookLanguages.Text=profile["languages"]?.ToString() ?? ""; BookYears.Text=profile["years"]?.ToString() ?? "";
            BookScript.Text=profile["script"]?.ToString() ?? ""; BookLayout.Text=profile["layout"]?.ToString() ?? "";
            BookModel.Text=profile["model"]?.ToString() ?? ""; BookNotes.Text=profile["notes"]?.ToString() ?? "";
            SetSelectedTag(BookSplit,profile["split"]?.ToString() ?? "");SetSelectedTag(BookCalendar,profile["calendar"]?.ToString() ?? "");
            await LoadSourceCard();
            await LoadPersonMentions();
            UpdateGuideHelp(); Status.Text=T("Готово");
            if(Environment.GetCommandLineArgs().Contains("--smoke-workbench"))
            {
                if(Environment.GetCommandLineArgs().Contains("--smoke-layout")) await InitializeLayoutSmoke();
                if(Environment.GetEnvironmentVariable("ARCHIVEREADER_SMOKE_COMPARE")=="1")
                {
                    ModelA.Text=ProjectModel("fondue-handwriting/model.mlmodel") ?? "";
                    ModelB.Text=ProjectModel("fondue-mixed/model.mlmodel") ?? "";
                    ShowComparison(await Call("compare_regions",new() { ["id"]=page.Id,["models"]=Models() }));
                }
                await RefreshPersonCandidates();
                Tabs.IsEnabled=true;
                UpdateLayout();
                var snapshotDirectory=System.IO.Path.Combine(System.IO.Path.GetDirectoryName(rendering["path"]!.ToString())!,"../workbench-ui");
                Directory.CreateDirectory(snapshotDirectory);
                for(int i=0;i<Tabs.Items.Count;i++)
                {
                    Tabs.SelectedIndex=i; UpdateLayout();
                    var shot=new RenderTargetBitmap((int)ActualWidth,(int)ActualHeight,96,96,PixelFormats.Pbgra32); shot.Render(this);
                    var png=new PngBitmapEncoder(); png.Frames.Add(BitmapFrame.Create(shot));
                    using(var stream=File.Create(System.IO.Path.Combine(snapshotDirectory,$"tab-{i}.png"))) png.Save(stream);
                }
                if(Environment.GetCommandLineArgs().Contains("--smoke-layout-review"))
                {
                    Tabs.SelectedIndex=6;LayoutReviewPanel.IsExpanded=true;await ReadLayoutQuality();await ReadBookQuality(0);LayoutReviewPanel.BringIntoView();await Dispatcher.InvokeAsync(()=>{},System.Windows.Threading.DispatcherPriority.ContextIdle);SmokeCapture.Save(this,"layout-workflow-ui","review.png");
                    LayoutReviewPanel.IsExpanded=false;LayoutComparePanel.IsExpanded=true;LayoutComparePanel.BringIntoView();await Dispatcher.InvokeAsync(()=>{},System.Windows.Threading.DispatcherPriority.ContextIdle);SmokeCapture.Save(this,"layout-workflow-ui","comparison.png");
                }
                if(Environment.GetCommandLineArgs().Contains("--smoke-page-review"))
                {
                    Tabs.SelectedIndex=6;PageReviewPanel.IsExpanded=true;SetPageReview(await Call("page_review_status",new(){["id"]=page.Id}));PageReviewPanel.BringIntoView();await Dispatcher.InvokeAsync(()=>{},System.Windows.Threading.DispatcherPriority.ContextIdle);SmokeCapture.Save(this,"page-review-ui","page.png");
                }
                Close();
            }
        });
        Closing+=(_,_)=>work?.Cancel();
    }
    static string? ProjectModel(string relative)
    {
        for(var folder=new DirectoryInfo(AppContext.BaseDirectory);folder!=null;folder=folder.Parent)
        { var path=System.IO.Path.Combine(folder.FullName,"models",relative.Replace('/',System.IO.Path.DirectorySeparatorChar)); if(File.Exists(path)) return path; }
        return null;
    }
    static BitmapImage Bitmap(string path)
    { var bitmap=new BitmapImage(); bitmap.BeginInit(); bitmap.CacheOption=BitmapCacheOption.OnLoad; bitmap.UriSource=new Uri(path); bitmap.EndInit(); bitmap.Freeze(); return bitmap; }
    static void SetSelectedTag(ComboBox box,string tag)
    { box.SelectedItem=box.Items.Cast<ComboBoxItem>().FirstOrDefault(i=>i.Tag?.ToString()==tag) ?? box.Items[0]; }
    async Task Run(Func<Task> action)
    {
        if(busy) return;
        busy=true; work=new CancellationTokenSource(); Tabs.IsEnabled=false;
        try { await action(); }
        catch(OperationCanceledException) { Status.Text=T("Обробку зупинено. Збережені результати залишилися в бібліотеці."); }
        catch(Exception ex)
        {
            Status.Text=T("Помилка: ")+T(ex.Message);
            if(Environment.GetCommandLineArgs().Contains("--smoke-workbench")) { File.WriteAllText(System.IO.Path.Combine(AppContext.BaseDirectory,"workbench-error.log"),ex.ToString()); Application.Current.Shutdown(1); }
            else MessageBox.Show(this,T(ex.Message),T("Майстерня документа"));
        }
        finally { Tabs.IsEnabled=true; work.Dispose(); work=null; busy=false; }
    }
    void CancelWork(object sender,RoutedEventArgs e)=>work?.Cancel();
    async Task RefreshRegions(string? selected=null)
    {
        var result=await Call("annotations",new() { ["id"]=page.Id });
        regions=result.AsArray().Select(n=>new RegionItem(n!.AsObject())).ToList();
        if(ReadingOrderRows!=null) ReadingOrderRows.ItemsSource=regions.Where(r=>r.Data["kind"]?.ToString() is "column" or "entry" or "line").OrderBy(r=>r.Data["reading_order"]?.GetValue<int>() ?? 100000).ToList();
        filling=true; Regions.ItemsSource=regions;
        ParentRegion.ItemsSource=new[] { new RegionItem(new JsonObject { ["label"]=T("Без зв'язку") }) }.Concat(regions.Where(r=>r.Data["kind"]?.ToString() is "entry" or "column")).ToList();
        ParentRegion.SelectedIndex=0; filling=false;
        Regions.SelectedItem=regions.FirstOrDefault(r=>r.Id==(selected ?? selectedRegion));
        DrawOverlays();
    }
    void SelectRegion(object sender,SelectionChangedEventArgs e)
    {
        if(filling || Regions.SelectedItem is not RegionItem item) return;
        selectedRegion=item.Id; var data=item.Data;
        var b=data["rect"]!.AsArray(); rectangle=new Rect(b[0]!.GetValue<double>(),b[1]!.GetValue<double>(),b[2]!.GetValue<double>(),b[3]!.GetValue<double>());
        RegionLabel.Text=data["label"]?.ToString() ?? ""; RegionText.Text=data["text"]?.ToString() ?? "";
        RegionVerified.IsChecked=data["verified"]?.GetValue<bool>()==true;
        ReadingPosition.Text=data["reading_order"]?.ToString() ?? "";
        SetSelectedTag(RegionKind,data["kind"]!.ToString()); SetSelectedTag(RegionField,data["field"]?.ToString() ?? "");
        ParentRegion.SelectedItem=ParentRegion.Items.Cast<RegionItem>().FirstOrDefault(r=>r.Id==(data["parent"]?.ToString() ?? ""));
        LinkedRecord.SelectedItem=LinkedRecord.Items.Cast<RecordItem>().FirstOrDefault(r=>(r.Data["id"]?.ToString() ?? "")== (data["record"]?.ToString() ?? ""));
        DrawOverlays();
    }
    void DrawOverlays()
    {
        foreach(var element in Surface.Children.OfType<Shape>().ToList()) Surface.Children.Remove(element);
        foreach(var element in Surface.Children.OfType<TextBlock>().ToList()) Surface.Children.Remove(element);
        foreach(var overlay in Surface.Children.OfType<Image>().Where(i=>i.Tag?.ToString()=="page-review-coverage").ToList())Surface.Children.Remove(overlay);
        if(Tabs.SelectedIndex==6&&pageReview?["coverage_path"] is JsonNode coverage&&File.Exists(coverage.ToString())&&pageReview["stale"]?.GetValue<bool>()!=true)
        {
            var overlay=new Image{Source=Bitmap(coverage.ToString()),Width=Surface.Width,Height=Surface.Height,Stretch=Stretch.Fill,IsHitTestVisible=false,Tag="page-review-coverage"};Surface.Children.Add(overlay);
            foreach(var node in pageReview["units"]!.AsArray())
            {var b=node!["rect"]!.AsArray();var color=node["state"]!.ToString() switch{"failed"=>Brushes.Red,"empty"=>Brushes.DarkOrange,"pending" or "running"=>Brushes.Gray,_=>Brushes.DodgerBlue};DrawRect(new Rect(b[0]!.GetValue<double>(),b[1]!.GetValue<double>(),b[2]!.GetValue<double>(),b[3]!.GetValue<double>()),color,2);}
            foreach(var node in pageReview["boxes"]!.AsArray())
            {var b=node!["rect"]!.AsArray();DrawRect(new Rect(b[0]!.GetValue<double>(),b[1]!.GetValue<double>(),b[2]!.GetValue<double>(),b[3]!.GetValue<double>()),node["state"]!.ToString()=="empty"?Brushes.DarkOrange:Brushes.Green,2);}
        }
        foreach(var region in regions)
        {
            var b=region.Data["rect"]!.AsArray();
            var color=layoutIssueIds.Contains(region.Id)||region.Data["kind"]?.ToString() is "damage" or "missing" ? Brushes.IndianRed : Brushes.DodgerBlue;
            DrawRect(new Rect(b[0]!.GetValue<double>(),b[1]!.GetValue<double>(),b[2]!.GetValue<double>(),b[3]!.GetValue<double>()),color,region.Id==selectedRegion ? 3 : 1);
            if(ShowReadingOrder?.IsChecked==true && Tabs.SelectedIndex==6 && region.Data["reading_order"] is JsonNode order)
            { var number=new TextBlock { Text=order.ToString(),FontSize=12,Background=Brushes.White,Foreground=Brushes.DarkBlue,IsHitTestVisible=false }; Canvas.SetLeft(number,b[0]!.GetValue<double>()*Surface.Width); Canvas.SetTop(number,b[1]!.GetValue<double>()*Surface.Height); Surface.Children.Add(number); }
        }
        if(Tabs.SelectedIndex==6)
            foreach(var draft in draftRegions)
            { var b=draft.Data["rect"]!.AsArray(); DrawRect(new Rect(b[0]!.GetValue<double>(),b[1]!.GetValue<double>(),b[2]!.GetValue<double>(),b[3]!.GetValue<double>()),Brushes.MediumPurple,1); }
        if(rectangle is Rect r) DrawRect(r,Brushes.DarkOrange,3);
        for(int i=0;i<points.Count;i++)
        {
            var dot=new Ellipse { Width=12,Height=12,Fill=Brushes.DarkOrange,IsHitTestVisible=false }; Canvas.SetLeft(dot,points[i].X*Surface.Width-6); Canvas.SetTop(dot,points[i].Y*Surface.Height-6); Surface.Children.Add(dot);
            var label=new TextBlock { Text=(i+1).ToString(),Foreground=Brushes.Black,Background=Brushes.White,IsHitTestVisible=false }; Canvas.SetLeft(label,points[i].X*Surface.Width+8); Canvas.SetTop(label,points[i].Y*Surface.Height); Surface.Children.Add(label);
        }
    }
    void DrawRect(Rect r,Brush color,double thickness)
    { var shape=new Rectangle { Width=r.Width*Surface.Width,Height=r.Height*Surface.Height,Stroke=color,StrokeThickness=thickness,IsHitTestVisible=false }; Canvas.SetLeft(shape,r.X*Surface.Width); Canvas.SetTop(shape,r.Y*Surface.Height); Surface.Children.Add(shape); }
    Point NormalizedPoint(MouseEventArgs e)
    { var p=e.GetPosition(Surface); return new Point(Math.Clamp(p.X/Surface.Width,0,1),Math.Clamp(p.Y/Surface.Height,0,1)); }
    void StartDraw(object sender,MouseButtonEventArgs e)
    {
        if(busy || PageImage.Source==null) return;
        if(Tabs.SelectedIndex==2 && SelectedTag(PhotoMode) is "perspective" or "dewarp")
        { if(points.Count < (SelectedTag(PhotoMode)=="perspective" ? 4 : 6)) points.Add(NormalizedPoint(e)); DrawOverlays(); UpdateGuideHelp(); return; }
        drag=NormalizedPoint(e); Surface.CaptureMouse();
    }
    void MoveDraw(object sender,MouseEventArgs e)
    { if(drag==null) return; rectangle=new Rect(drag.Value,NormalizedPoint(e)); DrawOverlays(); }
    void EndDraw(object sender,MouseButtonEventArgs e)
    { if(drag==null) return; rectangle=new Rect(drag.Value,NormalizedPoint(e)); drag=null; Surface.ReleaseMouseCapture(); DrawOverlays(); Status.Text=T("Межі виділено. Натисніть «Зберегти ділянку»."); }
    void NewRegion(object sender,RoutedEventArgs e)
    { selectedRegion=null; Regions.SelectedItem=null; rectangle=null; RegionLabel.Clear(); RegionText.Clear(); ReadingPosition.Clear(); RegionVerified.IsChecked=false; ParentRegion.SelectedIndex=0; LinkedRecord.SelectedIndex=0; DrawOverlays(); }
    async void SaveRegion(object sender,RoutedEventArgs e)=>await Run(async()=>
    {
        if(rectangle is not Rect r) throw new Exception(T("Спочатку виділіть ділянку мишею."));
        var data=new JsonObject { ["rect"]=new JsonArray(r.X,r.Y,r.Width,r.Height),["kind"]=SelectedTag(RegionKind),["label"]=RegionLabel.Text,["text"]=RegionText.Text,["verified"]=RegionVerified.IsChecked==true,
            ["parent"]=(ParentRegion.SelectedItem as RegionItem)?.Id,["record"]=(LinkedRecord.SelectedItem as RecordItem)?.Data["id"]?.ToString(),["field"]=SelectedTag(RegionField) };
        if(selectedRegion!=null && regions.FirstOrDefault(item=>item.Id==selectedRegion) is RegionItem previous)
            foreach(var field in previous.Data) if(!data.ContainsKey(field.Key) && field.Key!="id") data[field.Key]=field.Value?.DeepClone();
        if(ReadingPosition.Text.Length>0)
        { if(!int.TryParse(ReadingPosition.Text,out var position) || position<1 || position>100000) throw new Exception(T("Неправильний порядок читання.")); data["reading_order"]=position; }
        var result=await Call("save_annotation",new() { ["page"]=page.Id,["annotation"]=selectedRegion,["data"]=data });
        await RefreshRegions(result["id"]!.ToString()); Status.Text=T("Ділянку збережено.");
    });
    async void DeleteRegion(object sender,RoutedEventArgs e)=>await Run(async()=>
    { if(selectedRegion==null) return; await Call("delete_annotation",new() { ["page"]=page.Id,["annotation"]=selectedRegion }); selectedRegion=null; rectangle=null; await RefreshRegions(); });
    void ChooseModel(object sender,RoutedEventArgs e)
    {
        if(((Button)sender).Tag.ToString()=="Book")
        { var picker=new OpenFileDialog { Filter="Kraken|*.mlmodel;*.safetensors" }; if(picker.ShowDialog()==true) BookModel.Text=picker.FileName; return; }
        bool a=((Button)sender).Tag.ToString()=="A"; var engine=a ? EngineA : EngineB; var destination=a ? ModelA : ModelB;
        if(SelectedTag(engine)=="trocr") { var dialog=new OpenFolderDialog(); if(dialog.ShowDialog()==true) destination.Text=dialog.FolderName; }
        else { var dialog=new OpenFileDialog { Filter="Kraken|*.mlmodel;*.safetensors" }; if(dialog.ShowDialog()==true) destination.Text=dialog.FileName; }
    }
    JsonArray Models()
    {
        if(string.IsNullOrWhiteSpace(ModelA.Text) || string.IsNullOrWhiteSpace(ModelB.Text)) throw new Exception(T("Виберіть дві локальні моделі."));
        if(System.IO.Path.GetFullPath(ModelA.Text).Equals(System.IO.Path.GetFullPath(ModelB.Text),StringComparison.OrdinalIgnoreCase)) throw new Exception(T("Для порівняння виберіть різні моделі."));
        return new JsonArray(new JsonObject { ["name"]="A",["engine"]=SelectedTag(EngineA),["path"]=ModelA.Text },new JsonObject { ["name"]="B",["engine"]=SelectedTag(EngineB),["path"]=ModelB.Text });
    }
    async void CompareLine(object sender,RoutedEventArgs e)=>await Compare(false);
    async void ComparePage(object sender,RoutedEventArgs e)=>await Compare(true);
    async Task Compare(bool all)=>await Run(async()=>
    {
        if(!all && selectedRegion==null) throw new Exception(T("Спочатку виберіть збережений рядок."));
        Status.Text=T("Порівняння моделей…");
        var result=await Call("compare_regions",new() { ["id"]=page.Id,["annotation"]=all ? null : selectedRegion,["models"]=Models() }); ShowComparison(result);
    });
    void ShowComparison(JsonNode result)
    {
        reportPath=result["path"]!.ToString();
        ComparedLines.ItemsSource=result["rows"]!.AsArray().Select(n=>new ComparisonItem(n!.AsObject())).ToList(); ComparedLines.SelectedIndex=0;
        var summaries=new List<string>();
        foreach(var model in result["models"]!.AsArray())
        {
            summaries.Add(F("Модель {0}: CER {1}; рядків {2}; збоїв {3}.",model!["name"],Rate(model["micro_cer"]),model["scored_lines"],model["failed_lines"]));
        }
        if(result["paired"] is JsonNode paired) summaries.Add(F("Парна різниця CER A−B: {0}; інтервал: {1} … {2}; сторінок: {3}.",Rate(paired["difference"]),Rate(paired["lower_95"]),Rate(paired["upper_95"]),paired["pages"]));
        ComparisonSummary.Text=string.Join("\n",summaries);
        Status.Text=T("Порівняння завершено. Перевірте розбіжності за зображенням.");
    }
    void SelectComparison(object sender,SelectionChangedEventArgs e)
    {
        if(ComparedLines.SelectedItem is not ComparisonItem row) return;
        LinePreview.Source=Bitmap(row.Data["image"]!.ToString()); var results=row.Data["results"]!.AsObject();
        ResultA.Text=(results["A"]?["text"] ?? results["A"]?["error"])?.ToString() ?? "";
        ResultB.Text=(results["B"]?["text"] ?? results["B"]?["error"])?.ToString() ?? "";
        Highlight(ResultA,row.Data["differences"] as JsonArray,"a"); Highlight(ResultB,row.Data["differences"] as JsonArray,"b");
        var reference=row.Data["reference"]?.ToString();
        Difference.Text=reference==null ? T("Немає перевіреного еталона. Точність не обчислюється.") : T("Еталон: ")+reference+"\nCER A: "+Rate(results["A"]?["score"]?["cer"])+" · CER B: "+Rate(results["B"]?["score"]?["cer"]);
    }
    static string Rate(JsonNode? value)=>value==null ? "—" : (value.GetValue<double>()*100).ToString("F2")+"%";
    static void Highlight(TextBlock block,JsonArray? differences,string side)
    {
        var text=block.Text; block.Inlines.Clear(); int position=0;
        foreach(var item in differences ?? new JsonArray())
        {
            int start=item![side+"_start"]!.GetValue<int>(),end=item[side+"_end"]!.GetValue<int>();
            if(start>position) block.Inlines.Add(new Run(text[position..start]));
            if(end>start) block.Inlines.Add(new Run(text[start..end]) { Background=Brushes.Gold });
            else block.Inlines.Add(new Run("│") { Foreground=Brushes.IndianRed,ToolTip=Localizer.Text("У цьому прочитанні фрагмент відсутній.") });
            position=end;
        }
        if(position<text.Length) block.Inlines.Add(new Run(text[position..]));
    }
    void OpenReport(object sender,RoutedEventArgs e) { if(reportPath!=null) Process.Start(new ProcessStartInfo(reportPath) { UseShellExecute=true }); }
    void PhotoModeChanged(object sender,SelectionChangedEventArgs e) { if(GuideHelp==null) return; points.Clear(); photo=null; UpdateGuideHelp(); DrawOverlays(); }
    void UpdateGuideHelp()
    {
        GuideHelp.Text=T(SelectedTag(PhotoMode) switch { "perspective"=>"Позначте 4 кути: верхній лівий, верхній правий, нижній правий, нижній лівий.", "dewarp"=>"Позначте 6 точок: ліва, середня й права на верхній напрямній; потім відповідні точки на нижній.", _=>"Для повороту задайте кут; для розвороту — положення поділу." })+"\n"+points.Count;
    }
    void ClearPoints(object sender,RoutedEventArgs e) { points.Clear(); photo=null; DrawOverlays(); UpdateGuideHelp(); }
    async void PreparePhoto(object sender,RoutedEventArgs e)=>await Run(async()=>
    {
        if(!double.TryParse(AngleValue.Text.Replace(',','.'),NumberStyles.Float,CultureInfo.InvariantCulture,out var angle)) angle=Angle.Value;
        var guides=new JsonArray(); foreach(var p in points) guides.Add(new JsonArray(p.X,p.Y));
        photo=(await Call("prepare_photo",new() { ["id"]=page.Id,["mode"]=SelectedTag(PhotoMode),["angle"]=angle,["position"]=SplitPosition.Value,["points"]=guides })).AsObject();
        PhotoCopies.ItemsSource=photo["paths"]!.AsArray().Select(p=>new ComboBoxItem { Content=System.IO.Path.GetFileName(p!.ToString()),Tag=p.ToString() }).ToList();
        PhotoCopies.SelectedIndex=0;
        Status.Text=F("Підготовлено копій: {0}. Перевірте результат перед імпортом.",photo["paths"]!.AsArray().Count);
    });
    void SelectPhotoResult(object sender,SelectionChangedEventArgs e)
    { if(PhotoCopies.SelectedItem is ComboBoxItem item) PhotoResult.Source=Bitmap(item.Tag.ToString()!); }
    async void ImportPhoto(object sender,RoutedEventArgs e)=>await Run(async()=>
    { if(photo==null) throw new Exception(T("Спочатку підготуйте копію.")); await Call("import_derivative",photo.DeepClone().AsObject()); Status.Text=T("Похідні копії додано до бібліотеки з посиланням на джерело."); });
    JsonObject ProfileValues()=>new() { ["languages"]=BookLanguages.Text,["years"]=BookYears.Text,["script"]=BookScript.Text,["layout"]=BookLayout.Text,["model"]=BookModel.Text,["notes"]=BookNotes.Text,["split"]=SelectedTag(BookSplit),["calendar"]=SelectedTag(BookCalendar) };
    async void SaveProfile(object sender,RoutedEventArgs e)=>await Run(async()=> { await Call("book_profile",new() { ["id"]=page.Id,["values"]=ProfileValues() }); Status.Text=T("Профіль книги збережено."); });
    async void SearchNames(object sender,RoutedEventArgs e)=>await Run(async()=> { var results=await Call("similar_names",new() { ["query"]=NameQuery.Text }); NameResults.ItemsSource=results.AsArray().Select(n=>new NameMatch(n!.AsObject())).ToList(); });
    void GoToName(object sender,RoutedEventArgs e) { if(NameResults.SelectedItem is NameMatch name) { SelectedPageId=name.Data["page"]!.ToString(); SelectedRecordId=name.Data["record"]!.ToString(); Close(); } }
    async void ExportDataset(object sender,RoutedEventArgs e)
    { var dialog=new OpenFolderDialog { Title=T("Папка для навчального набору") }; if(dialog.ShowDialog()!=true) return; await Run(async()=> { var result=await Call("dataset_explicit",new() { ["path"]=dialog.FolderName }); Status.Text=F("Навчання: {0}; перевірка: {1}; тест: {2}; виключено: {3}.",result["train"],result["validation"],result["test"],result["excluded"]); }); }
    async void TrainExplicit(object sender,RoutedEventArgs e)=>await Run(async()=>
    {
        if(SelectedTag(EngineA)!="kraken") throw new Exception(T("Донавчання зараз підтримує Kraken."));
        var ketos=System.IO.Path.Combine(System.IO.Path.GetDirectoryName(PythonRuntime.Resolve()) ?? "","ketos.exe");
        Status.Text=T("Донавчання окремої копії. Журнал і контрольні точки зберігаються в бібліотеці.");
        var result=await Call("train_model",new() { ["model"]=ModelA.Text,["executable"]=ketos,["explicit"]=true });
        Status.Text=F("Донавчання завершено: {0}. Нову модель потрібно перевірити й вибрати вручну.",result["path"]);
    });
    async void CompareHeldout(object sender,RoutedEventArgs e)=>await Run(async()=> { Status.Text=T("Порівняння моделей…"); ShowComparison(await Call("heldout_compare",new() { ["models"]=Models() })); Tabs.SelectedIndex=1; });
    async void CompareFrozen(object sender,RoutedEventArgs e)
    {
        var dialog=new OpenFolderDialog { Title=T("Тестовий набір") }; if(dialog.ShowDialog()!=true) return;
        await Run(async()=> { Status.Text=T("Порівняння моделей…"); ShowComparison(await Call("benchmark_compare",new() { ["path"]=dialog.FolderName,["models"]=Models() })); Tabs.SelectedIndex=1; });
    }
}
