using System.IO;
using System.Text.Json.Nodes;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using System.Windows.Shapes;
using Microsoft.Win32;

namespace ArchiveReader;
public record GenealogyRow(JsonObject Data,string Label);
public partial class GenealogyWindow:Window
{
    readonly Func<string,JsonObject?,CancellationToken,Task<JsonNode>> worker;
    readonly string? page; Point? treeRootPoint; bool busy,filling,gedcomOptionsInitialized; List<GenealogyRow> people=[]; List<JsonObject> families=[];
    public string? SelectedPageId{get;private set;} public string? SelectedRecordId{get;private set;}
    static string T(string s)=>Localizer.Text(s);
    Task<JsonNode> Call(string command,JsonObject? args=null)=>worker(command,args,default);
    public GenealogyWindow(string? page,Func<string,JsonObject?,CancellationToken,Task<JsonNode>> worker)
    {this.page=page;this.worker=worker;InitializeComponent();Loaded+=async(_,_)=>await Run(async()=>{Localizer.Apply(this,Localizer.Language);await Refresh();await LoadMentions();if(Environment.GetCommandLineArgs().Contains("--show-couple-canvas")||Environment.GetCommandLineArgs().Contains("--smoke-evidence-canvas")){var largest=families.Where(f=>f["kind"]!.ToString()=="spouse").OrderByDescending(f=>(f["documents"] as JsonArray)?.Count??0).FirstOrDefault();if(largest!=null)OpenCanvas(new(){["family"]=largest["id"]!.ToString()});}if(Environment.GetCommandLineArgs().Contains("--show-tree"))Tabs.SelectedIndex=3;if(Environment.GetCommandLineArgs().Contains("--smoke-tree")){Tabs.IsEnabled=true;Tabs.SelectedIndex=3;await Dispatcher.InvokeAsync(()=>{},System.Windows.Threading.DispatcherPriority.ContextIdle);SmokeCapture.Save(this,"genealogy-ui","tree.png");Tabs.SelectedIndex=2;Families.SelectedItem=Families.Items.Cast<GenealogyRow>().FirstOrDefault(r=>r.Data["kind"]!.ToString()=="spouse"&&r.Data["status"]!.ToString()=="confirmed");FamilyDocuments.SelectedItem=FamilyDocuments.Items.Cast<GenealogyRow>().FirstOrDefault(r=>r.Data["text"]?.ToString().Contains("Zobowiązani")==true);SmokeCapture.Save(this,"genealogy-ui","couple-documents.png");Tabs.SelectedIndex=5;SmokeCapture.Save(this,"genealogy-ui","gedcom.png");if(FamilyDocuments.SelectedItem!=null)OpenFamilyRecord(this,new RoutedEventArgs());else Close();return;}if(Environment.GetCommandLineArgs().Contains("--smoke-roadmap")){FactField.SelectedIndex=2;await ShowFact();await PreviewGedcomFile(System.IO.Path.Combine(Environment.GetEnvironmentVariable("ARCHIVEREADER_DATA")!,"smoke-tree.ged"));Tabs.IsEnabled=true;Families.SelectedIndex=0;for(int i=0;i<Tabs.Items.Count;i++){Tabs.SelectedIndex=i;SmokeCapture.Save(this,"genealogy-ui",$"tab-{i}.png");}Close();}});}
    async Task Run(Func<Task> action){if(busy)return;busy=true;Tabs.IsEnabled=false;try{await action();}catch(Exception ex){Status.Text=T("Помилка: ")+T(ex.Message);SmokeCapture.Fail(ex);}finally{Tabs.IsEnabled=true;busy=false;}}
    string? PersonId=>(Persons.SelectedItem as GenealogyRow)?.Data["id"]?.ToString();
    async Task Refresh(string? ident=null)
    {
        ident??=PersonId;filling=true;
        people=(await Call("person_list")).AsArray().Select(n=>new GenealogyRow(n!.AsObject(),n["name"]!.ToString())).ToList();
        Persons.ItemsSource=people;FamilyLeft.ItemsSource=people;FamilyRight.ItemsSource=people;MergeTarget.ItemsSource=people;MergeTarget.SelectedIndex=0;
        Persons.SelectedItem=people.FirstOrDefault(p=>p.Data["id"]!.ToString()==ident) ?? people.FirstOrDefault(p=>p.Data["tree_root"]?.GetValue<bool>()==true) ?? people.FirstOrDefault();
        if(!gedcomOptionsInitialized){IncludeImportedGedcom.IsChecked=people.Any(p=>p.Data["tree_root"]?.GetValue<bool>()==true);IncludeGedcomMedia.IsChecked=true;gedcomOptionsInitialized=true;}
        FamilyLeft.SelectedIndex=0;FamilyRight.SelectedIndex=Math.Min(1,people.Count-1);filling=false;
        families=(await Call("family_list")).AsArray().Select(n=>n!.AsObject()).ToList();
        string Name(JsonNode? id)=>people.FirstOrDefault(p=>p.Data["id"]!.ToString()==id?.ToString())?.Label ?? "?";
        Families.ItemsSource=families.Select(f=>new GenealogyRow(f,$"{Name(f["left"])} {(f["kind"]!.ToString()=="parent" ? "→" : "↔")} {Name(f["right"])} · {T(f["status"]!.ToString() switch {"confirmed"=>"Підтверджено","imported"=>"Імпортовано зі схеми",_=>"Рішення відкликано"})} {(f["stale"]!.GetValue<bool>() ? "⚠" : "")}")).ToList();
        await LoadCard();DrawTree((await Call("family_tree")).AsObject());await LoadChanges();
    }
    async Task LoadCard()
    {
        if(PersonId==null){CardSummary.Text="";Members.ItemsSource=null;return;}
        FactImage.Source=null;MemberEvidence.Text="";
        var card=await Call("person_card",new(){["id"]=PersonId});PersonName.Text=card["name"]!.ToString();PersonNotes.Text=card["notes"]?.ToString() ?? "";
        CardSummary.Text=T("Варіанти імені")+": "+string.Join(", ",card["variants"]!.AsArray().Select(n=>n!.ToString()))+"\n"+string.Join("\n",card["variations"]!.AsObject().Select(pair=>ExtractionWindow.Field(pair.Key)+": "+string.Join(", ",pair.Value!.AsArray().Select(n=>n!.ToString()))));
        if(card["events"] is JsonArray imported)CardSummary.Text+="\n"+T("Події та джерела")+":\n"+string.Join("\n",imported.Select(n=>$"{n!["tag"]} · {n["date"]} · {n["place"]} · {n["citation"]}"));
        var members=card["members"]!.AsArray().Select(n=>new GenealogyRow(n!.AsObject(),$"{n["mention"]?["evidence"]?["date"]} · {n["mention"]?["name"]} · {n["mention"]?["document"]} {(n["stale"]!.GetValue<bool>() ? "⚠" : "")}")).ToList();Members.ItemsSource=members;SplitMembers.ItemsSource=members;Members.SelectedIndex=0;
        PersonDocuments.ItemsSource=card["documents"]!.AsArray().Select(n=>new GenealogyRow(n!.AsObject(),n["title"]!.ToString())).ToList();PersonDocuments.SelectedIndex=0;
    }
    async void SelectPerson(object sender,SelectionChangedEventArgs e){if(!filling)await Run(LoadCard);}
    void SelectPersonDocument(object sender,SelectionChangedEventArgs e)
    {
        PersonDocumentEvidence.Text=PersonDocuments.SelectedItem is GenealogyRow row ? row.Data["citation"]+"\n\n"+row.Data["text"] : "";
    }
    void OpenPersonDocument(object sender,RoutedEventArgs e)
    {
        if(PersonDocuments.SelectedItem is not GenealogyRow row)return;
        SelectedPageId=row.Data["page"]!.ToString();SelectedRecordId=row.Data["record"]?.ToString();DialogResult=true;
    }
    async void CreatePerson(object sender,RoutedEventArgs e)=>await Run(async()=>{var result=await Call("person_save",new(){["name"]=PersonName.Text,["notes"]=PersonNotes.Text});await Refresh(result["id"]!.ToString());});
    async void SavePerson(object sender,RoutedEventArgs e)=>await Run(async()=>{if(PersonId==null)return;await Call("person_save",new(){["id"]=PersonId,["name"]=PersonName.Text,["notes"]=PersonNotes.Text});await Refresh();});
    async Task LoadMentions(){var list=await Call("genealogy_mentions",new(){["page"]=page,["query"]=MentionQuery.Text});Mentions.ItemsSource=list.AsArray().Select(n=>new GenealogyRow(n!.AsObject(),$"{n["name"]} · {PersonMention.Role(n["field"]?.ToString())} · {n["document"]} · {n["number"]}")).ToList();Mentions.SelectedIndex=0;}
    async void FindMentions(object sender,RoutedEventArgs e)=>await Run(LoadMentions);
    static string RecordText(JsonNode record)=>string.Join("\n",new[]{"kind","date","person","related1","related2","age","place","house","text","notes"}.Select(key=>ExtractionWindow.Field(key)+": "+(key=="kind" ? T(record[key]?.ToString() ?? "") : record[key]?.ToString())));
    static string Evidence(JsonNode mention)=>$"{mention["name"]}\n{mention["citation"]}\n{RecordText(mention["evidence"]!)}";
    void SelectMention(object sender,SelectionChangedEventArgs e){if(Mentions.SelectedItem is GenealogyRow row)MentionEvidence.Text=Evidence(row.Data);}
    async void SelectMember(object sender,SelectionChangedEventArgs e){if(Members.SelectedItem is GenealogyRow row){MemberEvidence.Text=Evidence(row.Data["mention"]!)+"\n"+T("Пояснення рішення")+": "+row.Data["note"]+(row.Data["stale"]!.GetValue<bool>() ? "\n"+T("Записи змінилися: перевірте рішення повторно.") : "");await ShowFact();}}
    async void AttachMention(object sender,RoutedEventArgs e)=>await Run(async()=>{if(PersonId==null || Mentions.SelectedItem is not GenealogyRow row)return;await Call("person_attach",new(){["person"]=PersonId,["mention"]=row.Data.DeepClone(),["signature"]=row.Data["signature"]!.ToString(),["note"]=AttachReason.Text});await Refresh();});
    async void DetachMember(object sender,RoutedEventArgs e)=>await Run(async()=>{if(PersonId==null || Members.SelectedItem is not GenealogyRow row)return;await Call("person_detach",new(){["person"]=PersonId,["mention"]=row.Data["key"]!.ToString()});await Refresh();});
    void OpenMember(object sender,RoutedEventArgs e){if(Members.SelectedItem is GenealogyRow row){SelectedPageId=row.Data["mention"]!["page"]!.ToString();SelectedRecordId=row.Data["mention"]!["record"]!.ToString();DialogResult=true;}}
    async void SaveFamily(object sender,RoutedEventArgs e)=>await Run(async()=>
    {
        if(FamilyLeft.SelectedItem is not GenealogyRow left || FamilyRight.SelectedItem is not GenealogyRow right || Mentions.SelectedItem is not GenealogyRow evidence)return;
        var arguments=new JsonObject{["left"]=left.Data["id"]!.ToString(),["right"]=right.Data["id"]!.ToString(),["kind"]=((ComboBoxItem)FamilyKind.SelectedItem).Tag.ToString(),["record"]=evidence.Data["record"]!.ToString(),["signature"]=evidence.Data["signature"]!.ToString(),["note"]=FamilyReason.Text};
        if(Families.SelectedItem is GenealogyRow selected && selected.Data["status"]!.ToString()=="imported")arguments["id"]=selected.Data["id"]!.ToString();
        await Call("family_save",arguments);await Refresh();
    });
    void SelectFamily(object sender,SelectionChangedEventArgs e)
    {
        if(Families.SelectedItem is not GenealogyRow row)return;
        Families.ScrollIntoView(row);
        FamilyLeft.SelectedItem=people.FirstOrDefault(p=>p.Data["id"]!.ToString()==row.Data["left"]!.ToString());
        FamilyRight.SelectedItem=people.FirstOrDefault(p=>p.Data["id"]!.ToString()==row.Data["right"]!.ToString());
        FamilyKind.SelectedIndex=row.Data["kind"]!.ToString()=="parent"?0:1;
        FamilyReason.Text=row.Data["note"]?.ToString();
        FamilyEvidence.Text=$"{row.Data["citation"]}\n{row.Data["note"]}\n{RecordText(row.Data["evidence"]!)}";
        var documents=(row.Data["documents"] as JsonArray??new JsonArray()).Select(d=>new GenealogyRow(d!.AsObject(),d["title"]?.ToString()??d["citation"]!.ToString())).ToList();
        FamilyDocuments.ItemsSource=documents;
        FamilyDocuments.SelectedItem=documents.FirstOrDefault(d=>d.Data["record"]?.ToString()==row.Data["record"]?.ToString())??documents.FirstOrDefault();
    }
    async void WithdrawFamily(object sender,RoutedEventArgs e)=>await Run(async()=>
    {
        if(Families.SelectedItem is not GenealogyRow row)return;var data=row.Data.DeepClone().AsObject();data["status"]="withdrawn";data["note"]=FamilyReason.Text;await Call("family_save",data);await Refresh();
    });
    async void ExportGenealogy(object sender,RoutedEventArgs e)=>await Run(async()=>{var dialog=new SaveFileDialog{Filter="JSON|*.json",FileName="genealogy.json"};if(dialog.ShowDialog()==true)await Call("genealogy_export",new(){["path"]=dialog.FileName});});
    async void TreeTabChanged(object sender,SelectionChangedEventArgs e)
    {
        if(Tabs.SelectedIndex!=3)return;
        await Dispatcher.InvokeAsync(()=>
        {
            if(treeRootPoint is not Point point)return;
            TreeViewport.UpdateLayout();
            TreeViewport.ScrollToHorizontalOffset(Math.Max(0,point.X+112-TreeViewport.ViewportWidth/2));
            TreeViewport.ScrollToVerticalOffset(0);
        },System.Windows.Threading.DispatcherPriority.Loaded);
    }
    void OpenSourceBoard(object sender,RoutedEventArgs e)=>new BoardWindow(worker){Owner=this}.ShowDialog();
    void SelectFamilyDocument(object sender,SelectionChangedEventArgs e)
    {
        if(FamilyDocuments.SelectedItem is GenealogyRow document)
            FamilyEvidence.Text=document.Data["citation"]+"\n\n"+document.Data["text"];
    }
    void OpenFamilyRecord(object sender,RoutedEventArgs e)
    {
        JsonObject? data=(FamilyDocuments.SelectedItem as GenealogyRow)?.Data ?? (Families.SelectedItem as GenealogyRow)?.Data;
        if(data?["page"]==null)return;
        SelectedPageId=data["page"]!.ToString();SelectedRecordId=data["record"]?.ToString();DialogResult=true;
    }
    void ShowFamily(string id)
    {
        Families.SelectedItem=Families.Items.Cast<GenealogyRow>().FirstOrDefault(r=>r.Data["id"]!.ToString()==id);
        Tabs.SelectedIndex=2;
    }
    void OpenCanvas(JsonObject selection)=>new EvidenceCanvasWindow(worker,selection){Owner=this}.ShowDialog();
    void OpenPersonCanvas(object sender,RoutedEventArgs e){if(PersonId!=null)OpenCanvas(new(){["person"]=PersonId});}
    void OpenFamilyCanvas(object sender,RoutedEventArgs e){if(Families.SelectedItem is GenealogyRow row)OpenCanvas(new(){["family"]=row.Data["id"]!.ToString()});}
    void DrawTree(JsonObject layout)
    {
        Tree.Children.Clear();Tree.Width=layout["width"]?.GetValue<double>()??800;Tree.Height=layout["height"]?.GetValue<double>()??600;
        var positions=layout["nodes"]!.AsArray().ToDictionary(n=>n!["id"]!.ToString(),n=>new Point(n!["x"]!.GetValue<double>(),n["y"]!.GetValue<double>()));
        treeRootPoint=positions.TryGetValue(layout["root"]?.ToString()??"",out var focus)?focus:null;
        var active=families.Where(f=>f["status"]!.ToString() is "confirmed" or "imported").ToList();
        foreach(var f in active)
        {
            if(!positions.TryGetValue(f["left"]!.ToString(),out var left)||!positions.TryGetValue(f["right"]!.ToString(),out var right))continue;
            bool imported=f["status"]!.ToString()=="imported",stale=f["stale"]!.GetValue<bool>();
            var line=new Line{X1=left.X+112,Y1=left.Y+88,X2=right.X+112,Y2=right.Y+88,
                Stroke=imported?new SolidColorBrush(Color.FromRgb(179,179,179)):stale?Brushes.Gray:Brushes.SlateGray,StrokeThickness=3,
                ToolTip=T(imported?"Імпортовано зі схеми":"Підтверджено")};
            if(imported||stale)line.StrokeDashArray=new DoubleCollection{4,3};
            line.MouseLeftButtonDown+=(_,_)=>ShowFamily(f["id"]!.ToString());Tree.Children.Add(line);
            if(f["kind"]!.ToString()=="spouse" && f["documents"] is JsonArray documents && documents.Count>0)
            {
                var proof=new Button{Content=T("Документи пари")+" ("+documents.Count+")",Height=28,Padding=new Thickness(8,2,8,2)};
                proof.Click+=(_,_)=>OpenCanvas(new(){["family"]=f["id"]!.ToString()});Canvas.SetLeft(proof,Math.Min(left.X,right.X)+100);Canvas.SetTop(proof,Math.Max(left.Y,right.Y)+180);Tree.Children.Add(proof);
            }
        }
        foreach(var person in people)
        {
            if(!positions.TryGetValue(person.Data["id"]!.ToString(),out var point))continue;
            var style=person.Data["board_style"];var color=style?["color"];
            byte Channel(string key,double fallback)=>(byte)Math.Round((color?[key]?.GetValue<double>()??fallback)*255);
            var fill=new SolidColorBrush(Color.FromRgb(Channel("r",.89411765),Channel("g",.8),Channel("b",1)));
            string label=person.Data["tree_label"]?.ToString()??style?["text"]?.ToString()??person.Label;
            if(label.Split('\n')[0]!=person.Label)label=person.Label;
            var text=new TextBlock{Text=label,TextWrapping=TextWrapping.Wrap,TextAlignment=TextAlignment.Center,
                FontFamily=new FontFamily("Inter, Segoe UI"),FontSize=16,FontWeight=FontWeights.Medium,Foreground=new SolidColorBrush(Color.FromArgb(204,0,0,0))};
            var button=new Button{Content=text,Background=Brushes.Transparent,BorderThickness=new Thickness(0),Padding=new Thickness(16),ToolTip=person.Data["notes"]?.ToString()};
            button.Click+=(_,_)=>{Persons.SelectedItem=person;Tabs.SelectedIndex=0;};
            // Dimensions, palette and typography are taken from the owner's FigJam cards.
            var card=new Border{Width=224,Height=176,CornerRadius=new CornerRadius(12),Background=fill,Child=button};
            Canvas.SetLeft(card,point.X);Canvas.SetTop(card,point.Y);Tree.Children.Add(card);
        }
        if(layout["unconnected_generation"] is JsonNode generation)
        {
            var label=new TextBlock{Text=T("Зв’язок з основною гілкою ще не встановлено"),Foreground=Brushes.DimGray};
            Canvas.SetLeft(label,25);Canvas.SetTop(label,generation.GetValue<int>()*230+20);Tree.Children.Add(label);
        }
    }
}
