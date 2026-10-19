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
    readonly string? page; bool busy,filling; List<GenealogyRow> people=[]; List<JsonObject> families=[];
    public string? SelectedPageId{get;private set;} public string? SelectedRecordId{get;private set;}
    static string T(string s)=>Localizer.Text(s);
    Task<JsonNode> Call(string command,JsonObject? args=null)=>worker(command,args,default);
    public GenealogyWindow(string? page,Func<string,JsonObject?,CancellationToken,Task<JsonNode>> worker)
    {this.page=page;this.worker=worker;InitializeComponent();Loaded+=async(_,_)=>await Run(async()=>{Localizer.Apply(this,Localizer.Language);await Refresh();await LoadMentions();if(Environment.GetCommandLineArgs().Contains("--smoke-roadmap")){FactField.SelectedIndex=2;await ShowFact();await PreviewGedcomFile(System.IO.Path.Combine(Environment.GetEnvironmentVariable("ARCHIVEREADER_DATA")!,"smoke-tree.ged"));Tabs.IsEnabled=true;Families.SelectedIndex=0;for(int i=0;i<Tabs.Items.Count;i++){Tabs.SelectedIndex=i;SmokeCapture.Save(this,"genealogy-ui",$"tab-{i}.png");}Close();}});}
    async Task Run(Func<Task> action){if(busy)return;busy=true;Tabs.IsEnabled=false;try{await action();}catch(Exception ex){Status.Text=T("Помилка: ")+T(ex.Message);SmokeCapture.Fail(ex);}finally{Tabs.IsEnabled=true;busy=false;}}
    string? PersonId=>(Persons.SelectedItem as GenealogyRow)?.Data["id"]?.ToString();
    async Task Refresh(string? ident=null)
    {
        ident??=PersonId;filling=true;
        people=(await Call("person_list")).AsArray().Select(n=>new GenealogyRow(n!.AsObject(),n["name"]!.ToString())).ToList();
        Persons.ItemsSource=people;FamilyLeft.ItemsSource=people;FamilyRight.ItemsSource=people;MergeTarget.ItemsSource=people;MergeTarget.SelectedIndex=0;
        Persons.SelectedItem=people.FirstOrDefault(p=>p.Data["id"]!.ToString()==ident) ?? people.FirstOrDefault();
        FamilyLeft.SelectedIndex=0;FamilyRight.SelectedIndex=Math.Min(1,people.Count-1);filling=false;
        families=(await Call("family_list")).AsArray().Select(n=>n!.AsObject()).ToList();
        string Name(JsonNode? id)=>people.FirstOrDefault(p=>p.Data["id"]!.ToString()==id?.ToString())?.Label ?? "?";
        Families.ItemsSource=families.Select(f=>new GenealogyRow(f,$"{Name(f["left"])} {(f["kind"]!.ToString()=="parent" ? "→" : "↔")} {Name(f["right"])} · {T(f["status"]!.ToString() switch {"confirmed"=>"Підтверджено","imported"=>"Імпортовано, не підтверджено",_=>"Рішення відкликано"})} {(f["stale"]!.GetValue<bool>() ? "⚠" : "")}")).ToList();
        await LoadCard();DrawTree();await LoadChanges();
    }
    async Task LoadCard()
    {
        if(PersonId==null){CardSummary.Text="";Members.ItemsSource=null;return;}
        FactImage.Source=null;MemberEvidence.Text="";
        var card=await Call("person_card",new(){["id"]=PersonId});PersonName.Text=card["name"]!.ToString();PersonNotes.Text=card["notes"]?.ToString() ?? "";
        CardSummary.Text=T("Варіанти імені")+": "+string.Join(", ",card["variants"]!.AsArray().Select(n=>n!.ToString()))+"\n"+string.Join("\n",card["variations"]!.AsObject().Select(pair=>ExtractionWindow.Field(pair.Key)+": "+string.Join(", ",pair.Value!.AsArray().Select(n=>n!.ToString()))));
        if(card["events"] is JsonArray imported)CardSummary.Text+="\n"+T("Імпортовані неперевірені події")+":\n"+string.Join("\n",imported.Select(n=>$"{n!["tag"]} · {n["date"]} · {n["place"]} · {n["citation"]}"));
        var members=card["members"]!.AsArray().Select(n=>new GenealogyRow(n!.AsObject(),$"{n["mention"]?["evidence"]?["date"]} · {n["mention"]?["name"]} · {n["mention"]?["document"]} {(n["stale"]!.GetValue<bool>() ? "⚠" : "")}")).ToList();Members.ItemsSource=members;SplitMembers.ItemsSource=members;Members.SelectedIndex=0;
    }
    async void SelectPerson(object sender,SelectionChangedEventArgs e){if(!filling)await Run(LoadCard);}
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
    void SelectFamily(object sender,SelectionChangedEventArgs e){if(Families.SelectedItem is GenealogyRow row){FamilyEvidence.Text=$"{row.Data["citation"]}\n{row.Data["note"]}\n{RecordText(row.Data["evidence"]!)}";if(row.Data["status"]!.ToString()=="imported"){FamilyLeft.SelectedItem=people.FirstOrDefault(p=>p.Data["id"]!.ToString()==row.Data["left"]!.ToString());FamilyRight.SelectedItem=people.FirstOrDefault(p=>p.Data["id"]!.ToString()==row.Data["right"]!.ToString());FamilyKind.SelectedIndex=row.Data["kind"]!.ToString()=="parent" ? 0 : 1;}}}
    async void WithdrawFamily(object sender,RoutedEventArgs e)=>await Run(async()=>
    {
        if(Families.SelectedItem is not GenealogyRow row)return;var data=row.Data.DeepClone().AsObject();data["status"]="withdrawn";data["note"]=FamilyReason.Text;await Call("family_save",data);await Refresh();
    });
    async void ExportGenealogy(object sender,RoutedEventArgs e)=>await Run(async()=>{var dialog=new SaveFileDialog{Filter="JSON|*.json",FileName="genealogy.json"};if(dialog.ShowDialog()==true)await Call("genealogy_export",new(){["path"]=dialog.FileName});});
    void DrawTree()
    {
        Tree.Children.Clear();var levels=people.ToDictionary(p=>p.Data["id"]!.ToString(),_=>0);var active=families.Where(f=>f["status"]!.ToString()=="confirmed").ToList();
        for(int i=0;i<people.Count;i++)foreach(var f in active.Where(f=>f["kind"]!.ToString()=="parent"))if(levels.ContainsKey(f["left"]!.ToString()) && levels.ContainsKey(f["right"]!.ToString()))levels[f["right"]!.ToString()]=Math.Max(levels[f["right"]!.ToString()],levels[f["left"]!.ToString()]+1);
        var positions=new Dictionary<string,Point>();var counts=new Dictionary<int,int>();
        foreach(var p in people){int level=levels[p.Data["id"]!.ToString()];int column=counts.GetValueOrDefault(level);counts[level]=column+1;positions[p.Data["id"]!.ToString()]=new Point(25+column*220,35+level*130);}
        Tree.Width=Math.Max(800,(counts.Values.DefaultIfEmpty(0).Max())*220+40);Tree.Height=Math.Max(600,(levels.Values.DefaultIfEmpty(0).Max()+1)*130+40);
        foreach(var f in active){if(!positions.TryGetValue(f["left"]!.ToString(),out var left) || !positions.TryGetValue(f["right"]!.ToString(),out var right))continue;var line=new Line{X1=left.X+90,Y1=left.Y+25,X2=right.X+90,Y2=right.Y+25,Stroke=f["stale"]!.GetValue<bool>() ? Brushes.Gray : f["kind"]!.ToString()=="parent" ? Brushes.Teal : Brushes.MediumPurple,StrokeThickness=2};if(f["stale"]!.GetValue<bool>())line.StrokeDashArray=new DoubleCollection{4,3};Tree.Children.Add(line);}
        foreach(var p in people){var point=positions[p.Data["id"]!.ToString()];var button=new Button{Content=p.Label,Width=185,Height=50,Background=Brushes.AliceBlue};button.Click+=(_,_)=>{Persons.SelectedItem=p;Tabs.SelectedIndex=0;};Canvas.SetLeft(button,point.X);Canvas.SetTop(button,point.Y);Tree.Children.Add(button);}
    }
}
